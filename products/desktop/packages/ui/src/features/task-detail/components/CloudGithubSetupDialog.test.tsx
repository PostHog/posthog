import { useRendererWindowFocusStore } from "@posthog/ui/shell/rendererWindowFocusStore";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CloudGithubSetupDialog } from "./CloudGithubSetupDialog";

const connectState = vi.hoisted(() => ({
  error: null,
  isConnecting: false,
  isTimedOut: false,
  hasError: false,
  isPending: false,
  connect: vi.fn(async () => undefined),
  reset: vi.fn(),
  onConnected: null as (() => void) | null,
}));

vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (selector: (state: unknown) => unknown) =>
    selector({ currentProjectId: 1, cloudRegion: "us" }),
}));
vi.mock("@posthog/ui/features/integrations/useIntegrations", () => ({
  useRepositoryIntegration: () => ({ hasGithubIntegration: false }),
}));
vi.mock("@posthog/ui/features/integrations/useGithubUserConnect", () => ({
  useGithubConnect: ({ onConnected }: { onConnected?: () => void }) => {
    connectState.onConnected = onConnected ?? null;
    return connectState;
  },
}));
vi.mock("@posthog/ui/utils/browser", () => ({
  openUrlInBrowser: vi.fn(),
}));

describe("CloudGithubSetupDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    connectState.error = null;
    connectState.isConnecting = false;
    connectState.isTimedOut = false;
    connectState.hasError = false;
    connectState.isPending = false;
    connectState.onConnected = null;
    useRendererWindowFocusStore.setState({ focused: false });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts the GitHub connection", async () => {
    const user = userEvent.setup();
    render(
      <CloudGithubSetupDialog
        onConnected={vi.fn()}
        onContinueWithoutGithub={vi.fn()}
      />,
    );

    expect(
      screen.getByText("GitHub authentication required"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Cloud tasks require GitHub authentication."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Connect GitHub" }));

    expect(connectState.connect).toHaveBeenCalledOnce();
  });

  it("shows the onboarding visual while it waits for GitHub", () => {
    connectState.isConnecting = true;

    render(
      <CloudGithubSetupDialog
        onConnected={vi.fn()}
        onContinueWithoutGithub={vi.fn()}
      />,
    );

    const waitingState = screen
      .getByText("Waiting for GitHub")
      .closest('[data-slot="empty"]');
    expect(waitingState).toBeInTheDocument();
    expect(waitingState).toHaveTextContent(
      "Finish authorizing in your browser, then return here.",
    );
    expect(
      waitingState?.querySelector('[aria-label="Loading"]'),
    ).not.toBeNull();
  });

  it("cancels only after the user selects Cancel", async () => {
    const user = userEvent.setup();
    const onContinueWithoutGithub = vi.fn();
    render(
      <CloudGithubSetupDialog
        onConnected={vi.fn()}
        onContinueWithoutGithub={onContinueWithoutGithub}
      />,
    );

    expect(onContinueWithoutGithub).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onContinueWithoutGithub).toHaveBeenCalledOnce();
    expect(connectState.reset).toHaveBeenCalledOnce();
  });

  it("waits for window focus after the integration appears", () => {
    vi.useFakeTimers();
    const onConnected = vi.fn();
    const { rerender } = render(
      <CloudGithubSetupDialog
        hasGithubIntegration={false}
        onConnected={onConnected}
        onContinueWithoutGithub={vi.fn()}
      />,
    );

    rerender(
      <CloudGithubSetupDialog
        hasGithubIntegration
        onConnected={onConnected}
        onContinueWithoutGithub={vi.fn()}
      />,
    );
    expect(onConnected).not.toHaveBeenCalled();

    act(() => useRendererWindowFocusStore.setState({ focused: true }));

    act(() => vi.advanceTimersByTime(499));
    expect(screen.queryByText("GitHub connected")).not.toBeInTheDocument();
    expect(onConnected).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(1));

    expect(screen.getByText("GitHub connected")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "PostHog connected to GitHub" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cancel" }),
    ).not.toBeInTheDocument();
    expect(connectState.reset).toHaveBeenCalledOnce();
    expect(onConnected).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(1_199));
    expect(onConnected).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByText("GitHub connected")).toBeInTheDocument();
    expect(onConnected).toHaveBeenCalledOnce();
  });

  it("waits for window focus after the deep-link callback", () => {
    vi.useFakeTimers();
    const onConnected = vi.fn();
    render(
      <CloudGithubSetupDialog
        hasGithubIntegration={false}
        onConnected={onConnected}
        onContinueWithoutGithub={vi.fn()}
      />,
    );

    act(() => connectState.onConnected?.());
    expect(onConnected).not.toHaveBeenCalled();

    act(() => useRendererWindowFocusStore.setState({ focused: true }));

    expect(screen.queryByText("GitHub connected")).not.toBeInTheDocument();
    act(() => vi.advanceTimersByTime(500));
    expect(screen.getByText("GitHub connected")).toBeInTheDocument();
    expect(onConnected).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(1_200));
    expect(onConnected).toHaveBeenCalledOnce();
  });
});
