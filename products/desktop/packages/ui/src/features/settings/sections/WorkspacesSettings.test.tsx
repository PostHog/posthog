import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getWorktreeLocation = vi.hoisted(() => vi.fn());
const setWorktreeLocation = vi.hoisted(() => vi.fn());

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPCClient: () => ({
    os: {
      getWorktreeLocation: { query: getWorktreeLocation },
      setWorktreeLocation: { mutate: setWorktreeLocation },
      selectDirectory: { query: vi.fn() },
    },
    additionalDirectories: {
      listDefaults: { query: vi.fn().mockResolvedValue([]) },
      addDefault: { mutate: vi.fn() },
      removeDefault: { mutate: vi.fn() },
    },
  }),
}));

vi.mock("../../folder-picker/FolderPicker", () => ({
  FolderPicker: ({
    onChange,
    placeholder,
    value,
  }: {
    onChange: (path: string) => void;
    placeholder: string;
    value: string;
  }) => (
    <button
      type="button"
      onClick={() => onChange("/tmp/posthog-desktop/worktrees")}
    >
      {value || placeholder}
    </button>
  ),
}));

import { WorkspacesSettings } from "./WorkspacesSettings";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("WorkspacesSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getWorktreeLocation.mockResolvedValue("/tmp/existing-worktrees");
    setWorktreeLocation.mockResolvedValue(undefined);
  });

  it("loads and saves the runtime worktree location", async () => {
    const user = userEvent.setup();
    render(<WorkspacesSettings />, { wrapper });

    const picker = await screen.findByText("/tmp/existing-worktrees");
    await user.click(picker);

    await waitFor(() =>
      expect(setWorktreeLocation).toHaveBeenCalledWith({
        location: "/tmp/posthog-desktop/worktrees",
      }),
    );
  });
});
