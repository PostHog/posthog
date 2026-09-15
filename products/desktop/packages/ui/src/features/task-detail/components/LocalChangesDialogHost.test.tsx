import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useLocalChangesConfirmStore } from "../stores/localChangesConfirmStore";
import { LocalChangesDialogHost } from "./LocalChangesDialogHost";

const stashMock = vi.hoisted(() => vi.fn());
const trackMock = vi.hoisted(() => vi.fn());

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    focus: {
      stash: {
        mutationOptions: () => ({ mutationFn: stashMock }),
      },
    },
  }),
}));
vi.mock("../../../shell/analytics", () => ({ track: trackMock }));

function wrapper({ children }: { children: ReactNode }): React.JSX.Element {
  return (
    <QueryClientProvider client={new QueryClient()}>
      {children}
    </QueryClientProvider>
  );
}

describe("LocalChangesDialogHost", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useLocalChangesConfirmStore.setState({
      isOpen: false,
      repoPath: "",
      stagedFiles: [],
      unstagedFiles: [],
      untrackedFiles: [],
      resolve: null,
    });
  });

  it("stashes local changes before continuing", async () => {
    let resolveStash!: (result: { success: boolean }) => void;
    stashMock.mockImplementation(
      () =>
        new Promise<{ success: boolean }>((resolve) => {
          resolveStash = resolve;
        }),
    );
    const user = userEvent.setup();
    render(<LocalChangesDialogHost />, { wrapper });

    let confirmation!: Promise<string>;
    act(() => {
      confirmation = useLocalChangesConfirmStore.getState().confirm({
        repoPath: "/repo",
        stagedFiles: ["staged.ts"],
        unstagedFiles: [],
        untrackedFiles: ["new.ts"],
      });
    });

    await user.click(
      await screen.findByRole("button", { name: "Stash and continue" }),
    );

    await waitFor(() => {
      for (const action of ["cancel", "continue", "stash-and-continue"]) {
        expect(
          document.querySelector(`[data-attr="task-local-changes-${action}"]`),
        ).toHaveAttribute("aria-disabled", "true");
      }
    });
    await act(async () => {
      resolveStash({ success: true });
      await expect(confirmation).resolves.toBe("stash-and-continue");
    });
    expect(stashMock.mock.calls[0][0]).toEqual({
      repoPath: "/repo",
      message: "PostHog Desktop: local changes before task creation",
    });
  });

  it("keeps the dialog open when stashing fails", async () => {
    stashMock.mockResolvedValue({ success: false });
    const user = userEvent.setup();
    render(<LocalChangesDialogHost />, { wrapper });

    let confirmation!: Promise<string>;
    act(() => {
      confirmation = useLocalChangesConfirmStore.getState().confirm({
        repoPath: "/repo",
        stagedFiles: [],
        unstagedFiles: ["unstaged.ts"],
        untrackedFiles: [],
      });
    });

    await user.click(
      await screen.findByRole("button", { name: "Stash and continue" }),
    );

    expect(
      await screen.findByText(
        "Could not stash local changes. Check Git, then try again.",
      ),
    ).toBeInTheDocument();
    expect(useLocalChangesConfirmStore.getState().isOpen).toBe(true);

    await act(async () => {
      useLocalChangesConfirmStore.getState().cancel();
      await expect(confirmation).resolves.toBe("cancel");
    });
  });
});
