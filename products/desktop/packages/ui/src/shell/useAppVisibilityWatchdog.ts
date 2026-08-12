import { captureException } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import { type RefObject, useEffect } from "react";

const log = logger.scope("app-visibility");
const VISIBILITY_CHECK_DELAY_MS = 3000;

// Detects the "white screen but app alive" state: mounted and interactive yet stuck invisible.
export function useAppVisibilityWatchdog(
  ref: RefObject<HTMLElement | null>,
  active: boolean,
): void {
  useEffect(() => {
    if (!active) return;
    const timer = setTimeout(() => {
      const element = ref.current;
      if (!element) return;
      const computedOpacity = getComputedStyle(element).opacity;
      const opacity = computedOpacity ? Number.parseFloat(computedOpacity) : 1;
      const rect = element.getBoundingClientRect();
      if (opacity >= 0.01 && rect.width > 0 && rect.height > 0) return;
      const detail = {
        opacity,
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        route: window.location.hash,
      };
      log.error("Main app mounted but not visible", detail);
      captureException(new Error("Main app mounted but not visible"), {
        ...detail,
        source: "app-visibility-watchdog",
      });
    }, VISIBILITY_CHECK_DELAY_MS);
    return () => clearTimeout(timer);
  }, [ref, active]);
}
