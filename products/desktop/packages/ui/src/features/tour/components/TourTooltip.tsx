import { calculateTooltipPlacement } from "@posthog/core/tour/calculateTooltipPlacement";
import type { TooltipPlacement, TourStep } from "@posthog/core/tour/types";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { Button, Flex, Text, Theme } from "@radix-ui/themes";
import { AnimatePresence, motion, useAnimationControls } from "framer-motion";
import { useEffect } from "react";
import { createPortal } from "react-dom";

interface TourTooltipProps {
  step: TourStep;
  stepNumber: number;
  totalSteps: number;
  onDismiss: () => void;
  onNext: () => void;
  targetRect: DOMRect;
}

const HOG_SIZE = 64;
const HOG_GAP = 8;
const BUBBLE_MAX_WIDTH = 280;
const TOOLTIP_WIDTH_ESTIMATE = BUBBLE_MAX_WIDTH + HOG_GAP + HOG_SIZE;
const TOOLTIP_HEIGHT_ESTIMATE = 100;

const CARET_SIZE = 12;
const CARET_INNER = 11;

const talkingAnimation = {
  rotate: [0, -3, 3, -2, 2, 0],
  y: [0, -2, 0, -1, 0],
  transition: {
    duration: 0.4,
    repeat: Infinity,
    repeatDelay: 0.1,
  },
};

const hogEntranceVariants = {
  initial: { opacity: 0, scale: 0.5 },
  animate: {
    opacity: 1,
    scale: 1,
    transition: {
      type: "spring" as const,
      stiffness: 400,
      damping: 18,
      delay: 0.15,
    },
  },
  exit: {
    opacity: 0,
    scale: 0.5,
    transition: { duration: 0.1 },
  },
};

const CARET_SIDE_MAP: Record<
  TooltipPlacement,
  "left" | "right" | "top" | "bottom"
> = {
  right: "left",
  left: "right",
  bottom: "top",
  top: "bottom",
};

const TRANSFORM_ORIGIN_MAP: Record<TooltipPlacement, string> = {
  right: "left center",
  left: "right center",
  bottom: "top center",
  top: "bottom center",
};

function getBubbleVariants(placement: TooltipPlacement) {
  const dx = placement === "right" ? 12 : placement === "left" ? -12 : 0;
  const dy = placement === "bottom" ? -12 : placement === "top" ? 12 : 0;

  return {
    initial: { opacity: 0, scale: 0.92, x: dx, y: dy },
    animate: {
      opacity: 1,
      scale: 1,
      x: 0,
      y: 0,
      transition: { type: "spring" as const, stiffness: 300, damping: 24 },
    },
    exit: {
      opacity: 0,
      scale: 0.95,
      x: dx * 0.5,
      y: dy * 0.5,
      transition: { duration: 0.15 },
    },
  };
}

const COLORED_BORDER: Record<string, string> = {
  left: "borderRight",
  right: "borderLeft",
  top: "borderBottom",
  bottom: "borderTop",
};

function caretTriangle(
  side: "left" | "right" | "top" | "bottom",
  size: number,
  offset: number,
  color: string,
): React.CSSProperties {
  const isHorizontal = side === "left" || side === "right";
  const [t1, t2] = isHorizontal
    ? ["borderTop", "borderBottom"]
    : ["borderLeft", "borderRight"];

  return {
    position: "absolute",
    width: 0,
    height: 0,
    [isHorizontal ? "top" : "left"]: `calc(50% + ${offset}px)`,
    [side]: -size,
    [isHorizontal ? "marginTop" : "marginLeft"]: -size,
    [t1]: `${size}px solid transparent`,
    [t2]: `${size}px solid transparent`,
    [COLORED_BORDER[side]]: `${size}px solid ${color}`,
  };
}

function Caret({
  side,
  offset = 0,
}: {
  side: "left" | "right" | "top" | "bottom";
  offset?: number;
}) {
  return (
    <>
      <div style={caretTriangle(side, CARET_SIZE, offset, "var(--gray-a5)")} />
      <div
        style={caretTriangle(
          side,
          CARET_INNER,
          offset,
          "var(--color-panel-solid)",
        )}
      />
    </>
  );
}

export function TourTooltip({
  step,
  stepNumber,
  totalSteps,
  onDismiss,
  onNext,
  targetRect,
}: TourTooltipProps) {
  const isDarkMode = useThemeStore((s) => s.isDarkMode);
  const controls = useAnimationControls();

  const { placement, x, y, arrowOffset } = calculateTooltipPlacement(
    targetRect,
    TOOLTIP_WIDTH_ESTIMATE,
    TOOLTIP_HEIGHT_ESTIMATE,
    window.innerWidth,
    window.innerHeight,
    step.preferredPlacement,
  );

  const caretSide = CARET_SIDE_MAP[placement];
  const hogOnRight = true;
  const bubbleVariants = getBubbleVariants(placement);

  // biome-ignore lint/correctness/useExhaustiveDependencies: restart animation on step change
  useEffect(() => {
    controls.stop();
    const timer = setTimeout(() => {
      controls.start(talkingAnimation);
    }, 500);
    return () => clearTimeout(timer);
  }, [controls, step.id]);

  const hogElement = (
    <motion.div
      variants={hogEntranceVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      style={{
        ...(hogOnRight ? { marginLeft: HOG_GAP } : { marginRight: HOG_GAP }),
      }}
      className="shrink-0"
    >
      <motion.img
        src={step.hogSrc}
        alt=""
        animate={controls}
        style={{
          width: HOG_SIZE,
          height: HOG_SIZE,
        }}
        className="object-contain"
      />
    </motion.div>
  );

  return createPortal(
    <Theme
      appearance={isDarkMode ? "dark" : "light"}
      accentColor={isDarkMode ? "yellow" : "orange"}
      grayColor="slate"
      panelBackground="solid"
      radius="medium"
      className="pointer-events-none fixed top-0 left-0 z-[201]"
    >
      <AnimatePresence mode="wait">
        <div
          key={step.id}
          style={{ top: y, left: x }}
          className="pointer-events-auto fixed z-[201] flex items-center gap-0"
        >
          {!hogOnRight && hogElement}

          <motion.div
            variants={bubbleVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            style={{
              maxWidth: BUBBLE_MAX_WIDTH,
              boxShadow:
                "0 8px 24px rgba(0, 0, 0, 0.15), 0 2px 6px rgba(0, 0, 0, 0.08)",
              transformOrigin: TRANSFORM_ORIGIN_MAP[placement],
            }}
            className="relative rounded-(--radius-3) border border-(--gray-a5) bg-(--color-panel-solid) px-[18px] py-[14px]"
          >
            <Caret side={caretSide} offset={arrowOffset} />
            <Flex direction="column" gap="2">
              <Text className="text-(--gray-12) text-sm leading-normal">
                {step.message}
              </Text>
              <Flex justify="between" align="center" gap="3">
                <Text className="text-(--gray-9) text-[13px]">
                  {stepNumber}/{totalSteps}
                </Text>
                <Flex align="center" gap="2">
                  <Button
                    size="1"
                    variant="ghost"
                    color="gray"
                    onClick={onDismiss}
                    className="opacity-50"
                  >
                    Skip tour
                  </Button>
                  <Button size="1" variant="ghost" onClick={onNext}>
                    Next
                  </Button>
                </Flex>
              </Flex>
            </Flex>
          </motion.div>

          {hogOnRight && hogElement}
        </div>
      </AnimatePresence>
    </Theme>,
    document.body,
  );
}
