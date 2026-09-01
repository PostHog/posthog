import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/shell/analytics", () => ({
  captureException: vi.fn(),
}));

vi.mock("@posthog/ui/shell/logger", () => ({
  logger: {
    scope: () => ({
      error: vi.fn(),
      warn: vi.fn(),
      info: vi.fn(),
      debug: vi.fn(),
    }),
  },
}));

import { captureException } from "@posthog/ui/shell/analytics";
import {
  type AppLoadingGateState,
  useAppLoadingGateTelemetry,
} from "./useAppLoadingGateTelemetry";

const baseState: AppLoadingGateState = {
  isBootstrapped: true,
  isCheckingAccess: false,
  readyForMainApp: true,
  initialRouteLoaded: true,
  authStatus: "authenticated",
  desktopAccessStatus: "allowed",
  desktopAccessIsCurrent: true,
  consentStatus: "resolved",
};

describe("useAppLoadingGateTelemetry", () => {
  beforeEach(() => {
    vi.mocked(captureException).mockClear();
  });

  it("reports only when the main app drops back to the loading screen", () => {
    const { rerender } = renderHook(
      ({ showing, state }) => useAppLoadingGateTelemetry(showing, state),
      { initialProps: { showing: false, state: baseState } },
    );
    expect(captureException).not.toHaveBeenCalled();

    rerender({ showing: true, state: baseState });
    rerender({
      showing: true,
      state: { ...baseState, consentStatus: "loading" },
    });
    expect(captureException).not.toHaveBeenCalled();

    const hidden = {
      ...baseState,
      isCheckingAccess: true,
      desktopAccessStatus: "checking",
    };
    rerender({ showing: false, state: hidden });
    rerender({
      showing: false,
      state: { ...hidden, consentStatus: "loading" },
    });
    expect(captureException).toHaveBeenCalledTimes(1);
    expect(captureException).toHaveBeenCalledWith(
      expect.any(Error),
      expect.objectContaining({
        isCheckingAccess: true,
        desktopAccessStatus: "checking",
        source: "app-loading-gate",
      }),
    );
  });
});
