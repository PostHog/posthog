import { captureException } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import { useEffect, useRef } from "react";

const log = logger.scope("app-loading-gate");

export interface AppLoadingGateState {
  isBootstrapped: boolean;
  isCheckingAccess: boolean;
  readyForMainApp: boolean;
  initialRouteLoaded: boolean;
  authStatus: string;
  desktopAccessStatus: string;
  desktopAccessIsCurrent: boolean;
  consentStatus: string;
}

// Reports the main app dropping back to the full-window loading screen after
// it was already showing, with the gate inputs that caused it. Users see this
// as a brief logo flash, and the inputs are the only way to tell which one
// flipped.
export function useAppLoadingGateTelemetry(
  showingMainApp: boolean,
  state: AppLoadingGateState,
): void {
  const wasShowingMainApp = useRef(false);
  // Read through a ref so the effect fires on the transition only, not on
  // every input change while the app stays hidden.
  const stateRef = useRef(state);
  stateRef.current = state;
  useEffect(() => {
    if (showingMainApp) {
      wasShowingMainApp.current = true;
      return;
    }
    if (!wasShowingMainApp.current) return;
    wasShowingMainApp.current = false;
    const detail = { ...stateRef.current, route: window.location.hash };
    log.warn("Main app returned to loading screen", detail);
    captureException(new Error("Main app returned to loading screen"), {
      ...detail,
      source: "app-loading-gate",
    });
  }, [showingMainApp]);
}
