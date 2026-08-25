import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockGetTasks = vi.hoisted(() => vi.fn());
const mockGetCurrentUser = vi.hoisted(() => vi.fn());
const mockClient = vi.hoisted(() => ({
  getTasks: mockGetTasks,
  getCurrentUser: mockGetCurrentUser,
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));

import { useTasks } from "./useTasks";

describe("useTasks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetCurrentUser.mockResolvedValue({ id: 7 });
    mockGetTasks.mockResolvedValue([]);
  });

  function renderTasks(filters?: Parameters<typeof useTasks>[0]) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    return renderHook(() => useTasks(filters), { wrapper });
  }

  // Scout runs are created under the viewer's own id, so dropping this filter
  // refills the list they read as "my sessions" with unattended automation —
  // and in show-all-users mode, with every scout run on the team.
  it.each([
    ["own tasks", undefined],
    ["all users' tasks", { showAllUsers: true }],
  ])("excludes scout runs when listing %s", async (_name, filters) => {
    renderTasks(filters);

    await waitFor(() => expect(mockGetTasks).toHaveBeenCalled());
    expect(mockGetTasks).toHaveBeenCalledWith(
      expect.objectContaining({ excludeOriginProduct: "signals_scout" }),
    );
  });
});
