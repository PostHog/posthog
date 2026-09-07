import { getTour } from "@posthog/core/tour/tourRegistry";
import { useIsSettingsOpen } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useCommandMenuStore } from "@posthog/ui/shell/commandMenuStore";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { useElementRect } from "../hooks/useElementRect";
import { useTourStore } from "../tourStore";
import { TourTooltip } from "./TourTooltip";

const SPOTLIGHT_PADDING = 6;
const SPOTLIGHT_RADIUS = 8;

function SpotlightOverlay({ targetRect }: { targetRect: DOMRect | null }) {
  return createPortal(
    <AnimatePresence>
      {targetRect && (
        <motion.div
          key="spotlight"
          initial={{ opacity: 0 }}
          animate={{
            opacity: 1,
            top: targetRect.top - SPOTLIGHT_PADDING,
            left: targetRect.left - SPOTLIGHT_PADDING,
            width: targetRect.width + SPOTLIGHT_PADDING * 2,
            height: targetRect.height + SPOTLIGHT_PADDING * 2,
          }}
          exit={{ opacity: 0 }}
          transition={{ type: "spring", stiffness: 200, damping: 25 }}
          style={{
            borderRadius: SPOTLIGHT_RADIUS,
            boxShadow: "0 0 0 9999px rgba(0, 0, 0, 0.5)",
            zIndex: 199,
          }}
          className="pointer-events-none fixed"
        />
      )}
    </AnimatePresence>,
    document.body,
  );
}

export function TourOverlay() {
  const activeTourId = useTourStore((s) => s.activeTourId);
  const activeStepIndex = useTourStore((s) => s.activeStepIndex);
  const advance = useTourStore((s) => s.advance);
  const dismiss = useTourStore((s) => s.dismiss);

  useEffect(() => {
    if (!activeTourId) return;
    document.body.classList.add("tour-active");
    return () => document.body.classList.remove("tour-active");
  }, [activeTourId]);

  const tour = activeTourId ? getTour(activeTourId) : null;
  const step = tour?.steps[activeStepIndex] ?? null;

  const selector = step ? `[data-tour="${step.target}"]` : null;
  const targetRect = useElementRect(selector);

  const advancedRef = useRef(false);

  // biome-ignore lint/correctness/useExhaustiveDependencies: reset on step change
  useEffect(() => {
    advancedRef.current = false;
  }, [activeStepIndex]);

  useEffect(() => {
    if (!step || !activeTourId || step.advanceOn.type !== "click" || !selector)
      return;

    const el = document.querySelector(selector);
    if (!el) return;

    const tourId = activeTourId;
    const stepId = step.id;
    const handler = () => {
      if (!advancedRef.current) {
        advancedRef.current = true;
        advance(tourId, stepId);
      }
    };

    el.addEventListener("click", handler, { capture: true });
    return () => el.removeEventListener("click", handler, { capture: true });
  }, [step, selector, advance, activeTourId]);

  useEffect(() => {
    if (!step || !activeTourId || step.advanceOn.type !== "action" || !selector)
      return;

    const tourId = activeTourId;
    const stepId = step.id;
    const SETTLE_MS = 2000;
    let settleTimer: ReturnType<typeof setTimeout> | null = null;

    const tryAdvance = () => {
      const el = document.querySelector(selector);
      if (
        el?.getAttribute("data-tour-ready") === "true" &&
        !advancedRef.current
      ) {
        advancedRef.current = true;
        advance(tourId, stepId);
      }
    };

    const initialEl = document.querySelector(selector);
    if (initialEl?.getAttribute("data-tour-ready") === "true") {
      tryAdvance();
      return;
    }

    const onMutation = () => {
      if (settleTimer) clearTimeout(settleTimer);
      const el = document.querySelector(selector);
      if (el?.getAttribute("data-tour-ready") === "true") {
        settleTimer = setTimeout(tryAdvance, SETTLE_MS);
      }
    };

    const observer = new MutationObserver(onMutation);
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["data-tour-ready"],
    });

    return () => {
      observer.disconnect();
      if (settleTimer) clearTimeout(settleTimer);
    };
  }, [step, selector, advance, activeTourId]);

  const settingsOpen = useIsSettingsOpen();
  const commandMenuOpen = useCommandMenuStore((s) => s.isOpen);
  const overlayBlocked = settingsOpen || commandMenuOpen;
  const isActive = !!(tour && step && targetRect && !overlayBlocked);

  const handleNext = () => {
    if (activeTourId && step) {
      advancedRef.current = true;
      advance(activeTourId, step.id);
    }
  };

  return (
    <>
      <SpotlightOverlay targetRect={isActive ? targetRect : null} />
      {isActive && (
        <TourTooltip
          step={step}
          stepNumber={activeStepIndex + 1}
          totalSteps={tour.steps.length}
          onDismiss={dismiss}
          onNext={handleNext}
          targetRect={targetRect}
        />
      )}
    </>
  );
}
