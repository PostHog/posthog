import { Theme } from "@radix-ui/themes";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppLoadingScreen } from "./AppLoadingScreen";

vi.mock("@posthog/ui/shell/openExternal", () => ({
  openExternalUrl: vi.fn(),
}));

import { openExternalUrl } from "@posthog/ui/shell/openExternal";

const STALL_TIMEOUT_MS = 30_000;

function renderScreen() {
  return render(
    <Theme>
      <AppLoadingScreen />
    </Theme>,
  );
}

describe("AppLoadingScreen", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("renders the loading logo immediately", () => {
    renderScreen();
    expect(screen.getByTestId("app-loading-logo")).toBeInTheDocument();
    expect(
      screen.queryByText("PostHog is taking longer than expected to start"),
    ).not.toBeInTheDocument();
  });

  it("keeps the logo until just before the stall timeout", () => {
    renderScreen();
    act(() => {
      vi.advanceTimersByTime(STALL_TIMEOUT_MS - 1);
    });
    expect(screen.getByTestId("app-loading-logo")).toBeInTheDocument();
  });

  it("swaps to the stalled screen after the timeout", () => {
    renderScreen();
    act(() => {
      vi.advanceTimersByTime(STALL_TIMEOUT_MS);
    });
    expect(
      screen.getByText("PostHog is taking longer than expected to start"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Get support" }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("app-loading-logo")).not.toBeInTheDocument();
  });

  it("clears the stall timer on unmount", () => {
    const { unmount } = renderScreen();
    unmount();
    expect(() => {
      vi.advanceTimersByTime(STALL_TIMEOUT_MS);
    }).not.toThrow();
  });

  it("opens the support link from the stalled screen", () => {
    renderScreen();
    act(() => {
      vi.advanceTimersByTime(STALL_TIMEOUT_MS);
    });
    screen.getByRole("button", { name: "Get support" }).click();
    expect(openExternalUrl).toHaveBeenCalledWith(
      expect.stringContaining("discord"),
    );
  });
});
